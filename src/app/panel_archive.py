#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024 Wewoc (github.com/wewoc)

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
    QDialog, QListWidget, QMessageBox, QFrame, QTableWidgetItem, QInputDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

import garmin_app_controller as _controller
import garmin_quality as _quality
from .dialogs import PasswordConfirmDialog

_WCM_MIRROR_KEY = "gla_mirror_password"


class PanelArchive(QWidget):

    def __init__(self, app):
        super().__init__()
        self._app = app
        # Owner (D-4)
        self._mirror_running  = False
        self._silo_running    = False          # gate flag — silo check in progress
        self._last_silo_result: dict | None = None  # stale guard for repair
        # No UI widgets owned here — archive info labels live on PanelConnection
        # This panel owns the logic; PanelConnection owns the display labels.

    # ── Archive info ───────────────────────────────────────────────────────────

    def _refresh_archive_info(self):
        """Refresh archive info labels from quality_log.json (C1).
        Safe to call from any thread — dispatches UI update to Main Thread.
        Guard: skips silently if panel widgets have already been deleted
        (can happen during pytest-qt teardown when QTimer fires late)."""
        try:
            s = self._app._panel_settings._collect_settings()
        except RuntimeError:
            return
        base_dir = Path(s.get("base_dir", "")).expanduser()
        log_path = base_dir / "garmin_data" / "log" / "quality_log.json"

        if not log_path.exists():
            return
        try:
            stats = _quality.get_archive_stats(quality_log_path=log_path)
            if not stats.get("total"):
                return

            counts       = {"failed": stats.get("failed", 0)}
            # device_table — read directly from device_table.json (written by collector)
            _dt_path = base_dir / "garmin_data" / "log" / "device_table.json"
            try:
                device_table = json.loads(_dt_path.read_text(encoding="utf-8")) if _dt_path.exists() else []
            except Exception:
                device_table = []
            recheck  = stats["recheck"]
            missing  = stats["missing"] if stats["missing"] is not None else 0
            rng      = (f"{stats['date_min']} → {stats['date_max']}"
                        if stats["date_min"] and stats["date_max"] else "—")
            coverage = f"{stats['coverage_pct']}%" if stats["coverage_pct"] is not None else "—"
            last_api  = stats["last_api"]  or "—"
            last_bulk = stats["last_bulk"] or "—"

            # Source status — INTENTIONAL DIRECT READ via controller
            import app.garmin_app_controller as _ctrl
            src_stats   = _ctrl.get_source_stats(s)
            src_total   = src_stats.get("total", 0)
            src_present = src_stats.get("present", 0)
            source_text = f"Source: {src_total} days · {src_present}/180d"

            ph = self._app._panel_home
            integrity_warnings = stats.get("integrity_warnings", [])
            integrity_text = (
                "⚠  " + ", ".join(integrity_warnings)
                if integrity_warnings else ""
            )

            def _update():
                ph._info_qdots["failed"].setText(f"fail {counts['failed']}")
                ph._info_recheck.setText(f"Recheck: {recheck}")
                ph._info_missing.setText(f"Missing: {missing}")
                ph._info_range.setText(f"Range: {rng}")
                ph._info_coverage.setText(f"Coverage: {coverage}")
                ph._info_last_api.setText(f"Last API: {last_api}")
                ph._info_last_bulk.setText(f"Last Bulk: {last_bulk}")
                ph._info_source.setText(source_text)
                ph._integrity_warning_lbl.setText(integrity_text)

                # Device table — __total__ row is in device_table.json but
                # we render it separately for formatting control.
                tbl = ph._info_device_table
                tbl.setRowCount(0)
                total_high = total_std = total_all = 0
                data_rows = [r for r in device_table if r.get("device_id") != "__total__"]
                for row in data_rows:
                    r = tbl.rowCount()
                    tbl.insertRow(r)
                    tbl.setItem(r, 0, QTableWidgetItem(row.get("date_from") or "—"))
                    tbl.setItem(r, 1, QTableWidgetItem(row.get("date_to")   or "—"))
                    name_item = QTableWidgetItem(row.get("name") or row.get("device_id", "?"))
                    # Store device_id as UserRole — guard in name dialog uses this,
                    # not the display text, so renamed devices remain editable.
                    name_item.setData(Qt.ItemDataRole.UserRole, row.get("device_id"))
                    tbl.setItem(r, 2, name_item)
                    tbl.setItem(r, 3, QTableWidgetItem(str(row.get("days_high",     0) or "") or ""))
                    tbl.setItem(r, 4, QTableWidgetItem(str(row.get("days_standard", 0))))
                    tbl.setItem(r, 5, QTableWidgetItem(str(row.get("days_total",    0))))
                    for col in (3, 4, 5):
                        item = tbl.item(r, col)
                        if item:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    total_high += row.get("days_high",     0) or 0
                    total_std  += row.get("days_standard", 0) or 0
                    total_all  += row.get("days_total",    0) or 0
                # Summary row
                if data_rows:
                    r = tbl.rowCount()
                    tbl.insertRow(r)
                    tbl.setItem(r, 2, QTableWidgetItem("Total"))
                    tbl.setItem(r, 3, QTableWidgetItem(str(total_high) if total_high else ""))
                    tbl.setItem(r, 4, QTableWidgetItem(str(total_std)))
                    tbl.setItem(r, 5, QTableWidgetItem(str(total_all)))
                    for col in (2, 3, 4, 5):
                        item = tbl.item(r, col)
                        if item:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                            f = item.font()
                            f.setBold(True)
                            item.setFont(f)
                # Sizing: all columns fit content (set in panel_connection),
                # height fits exactly all rows — no scroll needed
                row_h  = tbl.verticalHeader().defaultSectionSize()
                hdr_h  = tbl.horizontalHeader().height()
                n_rows = tbl.rowCount()
                tbl.setFixedHeight(hdr_h + row_h * n_rows + 4)

                # Double-click on unknown row → name dialog (connect once)
                if not getattr(self, "_archive_device_click_connected", False):
                    tbl.cellDoubleClicked.connect(self._archive_on_device_name_click)
                    self._archive_device_click_connected = True

            self._app._dispatch(_update)

            # Mobile landing page — update status.json after every refresh
            try:
                import garmin_mobile_landing as _landing
                _landing.write_index_html(base_dir)
            except Exception:
                pass

        except Exception:
            pass

    # ── Device name dialog ────────────────────────────────────────────────────

    def _archive_on_device_name_click(self, row: int, col: int):
        """Double-click on device table row — opens name dialog for unknown devices.
        Main Thread only (signal always fires on Main Thread)."""
        ph  = self._app._panel_home
        tbl = ph._info_device_table
        name_item = tbl.item(row, 2)
        if name_item is None:
            return
        # Editable rows: device_id is None or a non-numeric sentinel like "__unknown__".
        # Rows with numeric Garmin device IDs or "__total__" are read-only.
        device_id = name_item.data(Qt.ItemDataRole.UserRole)
        if device_id is not None and (
            str(device_id).isdigit() or device_id == "__total__"
        ):
            return

        current = name_item.text()
        new_name, ok = QInputDialog.getText(
            self._app,
            "Device Name",
            "Name for unknown device:",
            text=current if current not in ("unknown", "?") else "",
        )
        if not ok or not new_name.strip():
            return

        s        = self._app._panel_settings._collect_settings()
        base_dir = Path(s.get("base_dir", "")).expanduser()
        log_path = base_dir / "garmin_data" / "log" / "quality_log.json"
        if not log_path.exists():
            return

        try:
            with _quality.QUALITY_LOCK:
                data = _quality._load_quality_log()
                updated = _quality.set_unknown_device_name(data, new_name.strip())
                if updated == 0:
                    return
                _quality._save_quality_log(data)
                _quality.save_device_table(data)
            self._app._log(
                f"✓ Device name set: '{new_name.strip()}' ({updated} entries updated)"
            )
        except Exception as e:
            self._app._log(f"✗ Device name update failed: {e}")
            return

        self._refresh_archive_info()

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
            result = _quality.cleanup_before_first_day(data, dry_run=False)
            dlg.accept()
            n_files   = result.get("files_deleted", 0)
            n_entries = result.get("entries_removed", 0)
            self._app._log(
                f"✓ Clean Archive: {n_files} files deleted, "
                f"{n_entries} log entries removed"
            )
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
        # INTENTIONAL DIRECT READ — read-only pre-flight check in GUI context.
        # No mutation, no ownership transfer, no QUALITY_LOCK required.
        # os.replace() atomicity guarantees reader sees either the old or the
        # new complete file — never a partial write.
        # garmin_quality provides no filtered count API for this query;
        # adding one would inflate the module into a query gateway.
        # Documented exception: see REFERENCE_GARMIN.md § Documented Exceptions.
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
                if e.get("quality", e.get("category", "")) == "failed"
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

    # ── Silo-Check ────────────────────────────────────────────────────────────

    def _on_silo_check(self):
        """Starts Silo-Check in background thread. Main Thread only."""
        if self._silo_running:
            return
        if self._mirror_running:
            QMessageBox.warning(self._app, "Silo-Check",
                "Mirror import is running.\nPlease wait until it finishes.")
            return
        if self._app._is_running():
            QMessageBox.warning(self._app, "Silo-Check",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Silo-Check",
                "Context sync is running.\nPlease wait until it finishes.")
            return
        if self._app._timer_active:
            QMessageBox.warning(self._app, "Silo-Check",
                "Background timer is active.\nStop the timer before running a silo check.")
            return

        self._silo_running = True
        self._last_silo_result = None
        self._app._dispatch(
            lambda: self._app._panel_connection.set_silo_check_button_state(
                False, text="🔍  Checking…"))
        self._app._dispatch(
            lambda: self._app._panel_connection.set_silo_repair_button_state(False))
        self._app._log("🔍  Silo-Check started …")

        def _do_check():
            try:
                import garmin_silo_check as _sc
                result = _sc.check_silos()
                self._last_silo_result = result

                t = result["totals"]
                c = result["counts"]
                total_findings = sum(c.values())

                lines = [
                    f"🔍  Silo-Check complete — {result['checked_at']}",
                    f"    raw={t['raw']}  summary={t['summary']}  "
                    f"source={t['source']}  quality_days={t['quality_days']}",
                ]
                if total_findings == 0:
                    lines.append("    ✓ No inconsistencies found.")
                else:
                    if c["raw_without_quality"]:
                        lines.append(
                            f"    ⚠ #1 raw without quality_log: "
                            f"{c['raw_without_quality']} day(s) — "
                            + ", ".join(d.isoformat()
                                        for d in result["raw_without_quality"][:5])
                            + ("…" if c["raw_without_quality"] > 5 else ""))
                    if c["source_without_raw"]:
                        lines.append(
                            f"    ⚠ #3 source without raw: "
                            f"{c['source_without_raw']} day(s) — "
                            + ", ".join(d.isoformat()
                                        for d in result["source_without_raw"][:5])
                            + ("…" if c["source_without_raw"] > 5 else ""))
                    if c["summary_without_raw"]:
                        lines.append(
                            f"    ⚠ #5 summary without raw: "
                            f"{c['summary_without_raw']} day(s) — "
                            + ", ".join(d.isoformat()
                                        for d in result["summary_without_raw"][:5])
                            + ("…" if c["summary_without_raw"] > 5 else ""))
                    if c["raw_without_summary"]:
                        lines.append(
                            f"    ⚠ #7 raw without summary: "
                            f"{c['raw_without_summary']} day(s) — "
                            + ", ".join(d.isoformat()
                                        for d in result["raw_without_summary"][:5])
                            + ("…" if c["raw_without_summary"] > 5 else ""))
                    lines.append(
                        "    → Use '🔧 Repair' to fix all findings.")

                for line in lines:
                    self._app._log_bg(line)

                has_findings = total_findings > 0
                self._app._dispatch(
                    lambda hf=has_findings: (
                        self._app._panel_connection.set_silo_check_button_state(
                            True, text="🔍  Silo-Check"),
                        self._app._panel_connection.set_silo_repair_button_state(
                            hf, text="🔧  Repair"),
                    ))

            except Exception as e:
                self._app._log_bg(f"✗ Silo-Check failed: {e}")
                self._app._dispatch(
                    lambda: self._app._panel_connection.set_silo_check_button_state(
                        True, text="🔍  Silo-Check"))
            finally:
                self._silo_running = False

        threading.Thread(target=_do_check, daemon=True).start()

    def _on_silo_repair(self):
        """Repair all silo findings. Main Thread only.
        Re-runs check_silos() first — never acts on stale findings (§9a)."""
        if self._silo_running:
            return
        if self._last_silo_result is None:
            self._app._log("✗ Silo-Repair: no check result available. Run Silo-Check first.")
            return
        if self._app._is_running() or self._app._ctx_running \
                or self._app._timer_active or self._mirror_running:
            QMessageBox.warning(self._app, "Silo-Repair",
                "A pipeline job is running.\nPlease wait until it finishes.")
            return

        self._silo_running = True
        self._app._dispatch(
            lambda: self._app._panel_connection.set_silo_repair_button_state(
                False, text="🔧  Repairing…"))
        self._app._dispatch(
            lambda: self._app._panel_connection.set_silo_check_button_state(False))
        self._app._log("🔧  Silo-Repair started — re-scanning first …")

        def _do_repair():
            import subprocess
            import sys as _sys

            try:
                import garmin_silo_check as _sc
                fresh = _sc.check_silos()
            except Exception as e:
                self._app._log_bg(f"✗ Silo-Repair: re-scan failed: {e}")
                self._app._dispatch(
                    lambda: (
                        self._app._panel_connection.set_silo_repair_button_state(
                            True, text="🔧  Repair"),
                        self._app._panel_connection.set_silo_check_button_state(True),
                    ))
                self._silo_running = False
                return

            ok = 0
            failed = 0
            s        = self._app._panel_settings._collect_settings()
            base_dir = Path(s.get("base_dir", "")).expanduser()

            # ── #3: source without raw → regenerate_raw.py --date ─────────────
            for d in fresh["source_without_raw"]:
                date_str = d.isoformat()
                try:
                    regen_script = base_dir.parent / "export" / "regenerate_raw.py"
                    if not regen_script.exists():
                        # Try relative to src/
                        import garmin_config as _cfg
                        regen_script = Path(_cfg.__file__).parent.parent / "export" / "regenerate_raw.py"
                    proc = subprocess.run(
                        [_sys.executable, str(regen_script), "--date", date_str],
                        capture_output=True, text=True, timeout=120,
                    )
                    if proc.returncode == 0:
                        self._app._log_bg(f"  ✓ #3 repaired: {date_str}")
                        ok += 1
                    else:
                        self._app._log_bg(
                            f"  ✗ #3 repair failed {date_str}: "
                            f"{proc.stderr.strip()[:200]}")
                        failed += 1
                except Exception as e:
                    self._app._log_bg(f"  ✗ #3 repair error {date_str}: {e}")
                    failed += 1

            # ── #5: summary without raw → unlink orphan ───────────────────────
            for d in fresh["summary_without_raw"]:
                date_str = d.isoformat()
                try:
                    import garmin_config as _cfg
                    orphan = _cfg.SUMMARY_DIR / f"garmin_{date_str}.json"
                    if orphan.exists():
                        orphan.unlink()
                        self._app._log_bg(f"  ✓ #5 orphan removed: {date_str}")
                        ok += 1
                    else:
                        self._app._log_bg(f"  ~ #5 already gone: {date_str}")
                except Exception as e:
                    self._app._log_bg(f"  ✗ #5 repair error {date_str}: {e}")
                    failed += 1

            # ── #7: raw without summary → inline summarize + write_day ─────────
            for d in fresh["raw_without_summary"]:
                date_str = d.isoformat()
                try:
                    import garmin_config as _cfg
                    import json as _json
                    raw_file = _cfg.RAW_DIR / f"garmin_raw_{date_str}.json"
                    if not raw_file.exists():
                        self._app._log_bg(f"  ~ #7 raw gone by now: {date_str}")
                        continue
                    raw = _json.loads(raw_file.read_text(encoding="utf-8"))
                    import garmin_normalizer as _norm
                    import garmin_writer as _writer
                    summary = _norm.summarize(raw)
                    _writer.write_day(raw, summary, date_str)
                    self._app._log_bg(f"  ✓ #7 summary rebuilt: {date_str}")
                    ok += 1
                except Exception as e:
                    self._app._log_bg(f"  ✗ #7 repair error {date_str}: {e}")
                    failed += 1

            # ── #1: raw without quality_log → _backfill_quality_log ───────────
            if fresh["raw_without_quality"]:
                try:
                    import garmin_quality as _quality
                    with _quality.QUALITY_LOCK:
                        qdata = _quality._load_quality_log()
                        added = _quality._backfill_quality_log(qdata)
                        if added:
                            _quality._save_quality_log(qdata)
                    self._app._log_bg(
                        f"  ✓ #1 quality_log backfilled: {added} entry(ies) added")
                    ok += added
                except Exception as e:
                    self._app._log_bg(f"  ✗ #1 repair error: {e}")
                    failed += 1

            self._app._log_bg(
                f"🔧  Silo-Repair complete — {ok} fixed, {failed} errors")

            self._last_silo_result = None
            self._app._dispatch(lambda: (
                self._app._panel_connection.set_silo_check_button_state(
                    True, text="🔍  Silo-Check"),
                self._app._panel_connection.set_silo_repair_button_state(
                    False, text="🔧  Repair"),
                self._app._panel_archive._refresh_archive_info(),
            ))
            self._silo_running = False

        threading.Thread(target=_do_repair, daemon=True).start()

    # ── Mirror check ───────────────────────────────────────────────────────────

    def _startup_mirror_check(self):
        """Checks at startup if mirror_dir is reachable (C3). Worker-safe.

        Path.exists() on Windows can block indefinitely for unreachable
        network paths (UNC, mapped drives, OneDrive). The check runs in
        a dedicated daemon thread with no join() — it dispatches the UI
        update whenever it completes, without blocking startup.

        Import from Mirror uses a file picker — button always enabled.
        Mirror (write) button depends on mirror_dir being reachable.
        """
        # Import button always active — user picks .gla via file dialog
        self._app._dispatch(
            lambda: self._app._panel_connection.set_import_mirror_button_state(True))

        s          = self._app._panel_settings._collect_settings()
        mirror_dir = s.get("mirror_dir", "").strip()

        if not mirror_dir:
            return

        def _check():
            reachable = False
            try:
                reachable = _controller.check_mirror(s)
            except Exception:
                pass

            self._app._dispatch(
                lambda: self._app._panel_connection.set_mirror_button_state(
                    reachable, text="⬡  Export to Mirror"))

        threading.Thread(target=_check, daemon=True).start()

    # ── Mirror operation ───────────────────────────────────────────────────────

    def _on_import_mirror(self):
        """Starts Mirror Import in background thread. Main Thread only."""
        if self._mirror_running:
            return

        from PyQt6.QtWidgets import QFileDialog
        mirror_path, _ = QFileDialog.getOpenFileName(
            self._app,
            "Select Mirror Container",
            "",
            "GLA Container (*.gla);;All Files (*)",
        )
        if not mirror_path:
            return

        s        = self._app._panel_settings._collect_settings()
        base_dir = Path(s.get("base_dir", "")).expanduser()

        if self._app._is_running():
            QMessageBox.warning(self._app, "Import from Mirror",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Import from Mirror",
                "Context sync is running.\nPlease wait until it finishes.")
            return

        # ── Password dialog — always manual for import ─────────────────────
        dlg = PasswordConfirmDialog(
            parent      = self,
            title       = "Mirror Password",
            heading     = "Mirror Container Password",
            description = (
                "Enter the password for the mirror container.\n"
                "This password protects data in transit (USB, NAS, cloud folder)."
            ),
            mode        = "unlock",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.get_result()

        # ── Dry-run: delta analysis before confirmation ────────────────────
        try:
            import garmin_import_mirror as _importer
            dry = _importer.run_import_mirror(
                mirror_path=Path(mirror_path),
                base_dir=base_dir,
                password=password,
                dry_run=True,
            )
        except Exception as e:
            QMessageBox.critical(self._app, "Import from Mirror",
                                 f"Dry-run failed:\n{e}")
            return

        if not dry.get("ok"):
            QMessageBox.critical(self._app, "Import from Mirror",
                "Could not read mirror data.\nCheck log for details.")
            return

        raw_n    = dry.get("raw_to_copy", 0)
        ctx_n    = dry.get("context_to_copy", 0)
        ver_warn = dry.get("version_warning", "")

        msg = f"{raw_n} raw day(s) and {ctx_n} context file(s) will be imported."
        if ver_warn:
            msg += f"\n\n⚠ {ver_warn}"
        msg += "\n\nProceed?"

        answer = QMessageBox.question(
            self._app, "Import from Mirror", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        # ── Pause timer, run import ────────────────────────────────────────
        timer_was_active = self._app._timer_active
        if self._app._timer_active:
            self._app._log("⏱  Background timer paused for mirror import.")
            self._app._timer_stop.set()
            self._app._timer_active = False
            self._app._dispatch(self._app._panel_timer._timer_update_btn)

        self._mirror_running = True
        self._app._panel_connection.set_import_mirror_button_state(False)
        self._app._log("📥  Import from Mirror started …")

        def _do_import():
            try:
                import garmin_import_mirror as _imp
                result = _imp.run_import_mirror(
                    mirror_path=Path(mirror_path),
                    base_dir=base_dir,
                    password=password,
                    dry_run=False,
                )
                msg = (
                    f"✓ Mirror import complete: "
                    f"{result['raw_copied']} raw day(s) imported, "
                    f"{result['raw_skipped']} skipped, "
                    f"{result['context_copied']} context file(s) imported"
                )
                if result["errors"]:
                    msg += f", {result['errors']} error(s)"
                self._app._log_bg(msg)
            except Exception as e:
                self._app._log_bg(f"✗ Mirror import failed: {e}")
            finally:
                self._mirror_running = False
                self._app._dispatch(lambda: (
                    self._app._panel_archive._refresh_archive_info(),
                    self._app._panel_timer._timer_resume_after_sync(timer_was_active),
                    self._app._panel_connection.set_import_mirror_button_state(True),
                ))

        threading.Thread(target=_do_import, daemon=True).start()

    def _on_mirror(self):
        """Starts mirror operation in background thread (C4/C5). Main Thread only."""
        if self._mirror_running:
            return
        s            = self._app._panel_settings._collect_settings()
        mirror_path  = s.get("mirror_dir", "").strip()
        if not mirror_path:
            QMessageBox.warning(self._app, "Export to Mirror",
                                "No mirror target configured.")
            return
        base_dir = Path(s.get("base_dir", "")).expanduser()

        if self._app._is_running():
            QMessageBox.warning(self._app, "Export to Mirror",
                "A Garmin sync is currently running.\nPlease wait until it finishes.")
            return
        if self._app._timer_active:
            QMessageBox.warning(self._app, "Export to Mirror",
                "Background timer is active.\nStop the timer before mirroring.")
            return
        if self._app._ctx_running:
            QMessageBox.warning(self._app, "Export to Mirror",
                "Context sync is running.\nPlease wait until it finishes.")
            return

        # ── Password: always prompt — no WCM caching ──────────────────────────
        dlg = PasswordConfirmDialog(
            parent      = self,
            title       = "Mirror Password",
            heading     = "Mirror Container Password",
            description = (
                "Enter the password for the mirror container.\n"
                "This password protects data in transit (USB, NAS, cloud folder)."
            ),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.get_result()

        self._mirror_running = True
        self._app._panel_connection.set_mirror_button_state(
            False, text="🔁  Mirroring…")
        self._app._log("🔁  Data Mirror started …")

        def _do_mirror():
            try:
                import garmin_mirror as _mirror
                result = _mirror.run_mirror(base_dir, Path(mirror_path), password)
                msg = (
                    f"✓ Mirror complete: {result.get('files_packed', 0)} files packed"
                )
                if result.get("errors"):
                    msg += f", {result['errors']} errors"
                self._app._log_bg(msg)
            except Exception as e:
                self._app._log_bg(f"✗ Mirror failed: {e}")
            finally:
                self._mirror_running = False
                self._app._dispatch(
                    lambda: self._app._panel_connection.set_mirror_button_state(
                        True, text="⬡  Export to Mirror"))

        threading.Thread(target=_do_mirror, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  Module-level helpers — WCM for mirror password
# ══════════════════════════════════════════════════════════════════════════════

def _archive_load_mirror_password() -> str | None:
    """Loads mirror password from WCM. Returns None if not stored."""
    try:
        import keyring
        return keyring.get_password("garmin_local_archive", _WCM_MIRROR_KEY)
    except Exception:
        return None


def _archive_save_mirror_password(password: str) -> None:
    """Saves mirror password to WCM. Silent on failure."""
    try:
        import keyring
        keyring.set_password("garmin_local_archive", _WCM_MIRROR_KEY, password)
    except Exception:
        pass
