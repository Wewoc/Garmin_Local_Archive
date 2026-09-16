#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wewoc (github.com/wewoc)

"""
compiler/build_gui.py
Garmin Local Archive — Build GUI ("🦄 Garmin Local Archiv Builder")

Run with:
    python compiler/build_gui.py

Wraps Timo's existing manual build workflow (copy the working tree into
a separate build folder so build artefacts never land inside the
working directory, then run compiler/build_all.py there — via
bat/run_build_all.bat's own "Qt tests first, then build_all.py"
sequence) into one Tkinter window (garmin_collector-3_experiment,
Baustein 31). Grew out of two independent, already-experienced pain
points:

  1. A stale-copy bug: a manual copy Timo believed was fresh still held
     an older compiler/build_all.py, and the resulting confusion
     (missing log timestamps) took a real diff to track down — see
     PROTOKOLL_experiment.md. Folding the copy step into the same tool
     that runs the build removes this whole class of error: the copy
     source is always THIS repo, right now, never a manually re-copied
     folder that might be stale.
  2. build_all.py's own logging (the _Tee/phase()/run_and_tee() work,
     same session) never captured PyInstaller's own console output —
     compiler/build.py's/compiler/build_standalone.py's build_exe()
     calls subprocess.run(cmd, cwd=str(root)) without stdout=PIPE, so
     PyInstaller inherits the real console handle directly, bypassing
     any Python-level sys.stdout redirection entirely. Deliberately
     NOT fixed there — would mean touching build_exe() itself, a
     separate change. This GUI sidesteps the problem structurally
     instead: it runs build_all.py as ONE subprocess with its stdout
     captured — PyInstaller, as a GRANDCHILD of this GUI process
     (build_all.py's own child), inherits the SAME redirected file
     descriptor, so its output reaches this window's log exactly like
     build_all.py's own print()s do, with no change needed to
     build_exe() at all.

Elapsed-time stopwatch, not wall-clock timestamps (Timo: "es reicht
wenn es eine Art Stoppuhr ist — verstrichene Zeit seit Build-Start,
damit man sehen kann wie lange es dauert und wo es evtl hängt") — each
log line is prefixed with [H:MM:SS] counted from this window's own
Start click, not the time of day.

Destructive by design: the chosen build directory's existing content
is deleted before the working directory is copied in — always behind
an explicit confirmation dialog naming the exact path, never silent.
Two additional guard checks before that dialog even appears: the
target must not be the working directory (or a folder inside it —
would recurse into itself / delete the source), and the working
directory must not be inside the target (would delete the source when
the target is cleared).

Cancel/Stop only becomes available once a subprocess (the Qt-test
gate or the build itself) is actually running, not during the initial
copy (expected to be far shorter than the build) — taskkill /PID <pid>
/T /F, same tree-kill technique clients/mcp_process.py::
_kill_pid_tree() already uses and for the same reason: both
bat/run_build_all.bat's pytest step and build_all.py itself spawn
further child processes (PyInstaller itself, in build_all.py's case)
that a plain Popen.terminate() would not reach.

The shared build venv (compiler/build_manifest.py::BUILD_VENV_DIR,
D:\\Garmin\\.venv_gla) is untouched by this tool — only the source tree
is copied; compiler/build.py's/build_standalone.py's own
ensure_build_venv() still finds and reuses the one shared venv exactly
as before, regardless of which folder the build runs from.

Tkinter, not PyQt6 — matches clients/mcp_server_gui.py's own reasoning
(a build tool has no need for PyQt6/WebEngine either), and this script
is never embedded in any T2/T3 build artefact itself (compiler/ is
build-tooling only, never shipped, not part of SHARED_SCRIPTS), so it
adds no bundling weight to worry about either way.
"""

import os
import queue
import shutil
import stat
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# compiler/build_gui.py -> compiler/ -> src/ -> repo root. The "working
# directory" this tool copies is always the repo root containing THIS
# script, never user-selectable — see module docstring, pain point 1
# (a stale/wrong copy source was exactly the bug this tool exists to
# prevent).
WORK_DIR = Path(__file__).resolve().parent.parent.parent

# Left behind by earlier manual builds/dev use in the working
# directory — copying them into a fresh build folder would only waste
# time and disk, never help (the build regenerates its own artefacts;
# .git/__pycache__ have no bearing on the build itself).
_COPY_EXCLUDES = {".git", "__pycache__"}


def _elapsed_str(start: float) -> str:
    total = int(time.monotonic() - start)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]"


def _copy_ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in _COPY_EXCLUDES}


def _clear_readonly_and_retry(func, path, exc) -> None:
    """shutil.rmtree()'s onexc callback (Python 3.12+) — Windows does
    NOT let a read-only file be deleted; shutil.rmtree() does not clear
    that attribute on its own and instead raises immediately, on the
    very first read-only file it hits (garmin_collector-3_experiment,
    Baustein 33: reproduced live with no locking process involved —
    Timo explicitly ruled that out — and failing instantly, at
    [0:00:00], rather than after _mkdir_with_retry()'s several seconds
    of retries, which pointed at rmtree() itself rather than the
    mkdir() race Baustein 32 fixed). Standard Windows-safe rmtree
    idiom: clear the attribute, then retry the exact operation that
    just failed (func is os.remove/os.rmdir/os.unlink, path is the
    file/dir that raised)."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _mkdir_with_retry(target: Path, retries: int = 8, delay: float = 0.5,
                       on_retry=None) -> None:
    """Creates target, retrying on a transient WinError 5 — Windows can
    briefly refuse to recreate a directory immediately after
    shutil.rmtree() just deleted it (Explorer/antivirus still holding
    a stale handle on the old one), even though the deletion itself
    fully succeeded. Not a code bug in the delete step — observed live
    (garmin_collector-3_experiment, Baustein 32): "die dateien aus
    test3/ wurden gelöscht der fehler kam erst nach dem löschen".
    8 * 0.5s = 4s total budget, generous for what is normally a
    sub-second race; re-raises the last error if it never clears."""
    last_exc: OSError | None = None
    for attempt in range(retries):
        try:
            target.mkdir(parents=True, exist_ok=True)
            return
        except OSError as exc:
            last_exc = exc
            if on_retry is not None:
                on_retry(attempt + 1, retries)
            time.sleep(delay)
    raise last_exc


def run_gui() -> None:
    root = tk.Tk()
    root.title("🦄 Garmin Local Archiv Builder")
    root.geometry("820x640")

    ttk.Label(
        root, text="🦄  GARMIN LOCAL ARCHIV BUILDER",
        font=("Segoe UI", 13, "bold"),
    ).pack(anchor="w", padx=10, pady=(10, 0))

    ttk.Label(root, text=f"Arbeitsverzeichnis: {WORK_DIR}").pack(
        anchor="w", padx=10, pady=(4, 0))

    # ── Build-Zielverzeichnis + Start/Abbrechen ─────────────────────────
    target_frame = ttk.Frame(root, padding=10)
    target_frame.pack(fill="x")
    ttk.Label(target_frame, text="Build-Zielverzeichnis:").grid(
        row=0, column=0, sticky="w")
    target_var = tk.StringVar(value="")
    ttk.Entry(target_frame, textvariable=target_var, width=70).grid(
        row=0, column=1, sticky="we", padx=(6, 6))

    def _browse_target():
        chosen = filedialog.askdirectory(
            initialdir=target_var.get() or str(WORK_DIR.parent))
        if chosen:
            target_var.set(chosen)

    ttk.Button(target_frame, text="…", width=3, command=_browse_target).grid(
        row=0, column=2)
    target_frame.columnconfigure(1, weight=1)

    start_btn = ttk.Button(target_frame, text="Build starten")
    start_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))
    cancel_btn = ttk.Button(target_frame, text="Abbrechen", state="disabled")
    cancel_btn.grid(row=1, column=1, sticky="w", pady=(8, 0), padx=(6, 0))

    status_var = tk.StringVar(value="")
    ttk.Label(root, textvariable=status_var).pack(anchor="w", padx=10)

    # ── Log section ──────────────────────────────────────────────────────
    log_bar = ttk.Frame(root, padding=(10, 4))
    log_bar.pack(fill="x")
    ttk.Label(log_bar, text="LOG", font=("Segoe UI", 8, "bold")).pack(side="left")

    def _clear_log():
        log_widget.configure(state="normal")
        log_widget.delete("1.0", tk.END)
        log_widget.configure(state="disabled")

    ttk.Button(log_bar, text="Clear", command=_clear_log).pack(side="right")

    log_widget = scrolledtext.ScrolledText(
        root, height=24, state="disabled", font=("Consolas", 9),
        background="#0a0a1a", foreground="#33ff66")
    log_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ── State shared across the closures below ──────────────────────────
    proc_state = {"pid": None}
    build_start = {"t": None}
    log_file_handle = {"fh": None}

    def _log_raw(line: str):
        """Appends a line as-is — no elapsed-time prefix. Used before a
        build has actually started (copy phase, upfront errors), where
        a stopwatch reading would be meaningless."""
        log_widget.configure(state="normal")
        log_widget.insert(tk.END, line + "\n")
        log_widget.see(tk.END)
        log_widget.configure(state="disabled")
        if log_file_handle["fh"] is not None:
            log_file_handle["fh"].write(line + "\n")
            log_file_handle["fh"].flush()

    def _log(line: str):
        """Appends a line prefixed with elapsed time since build_start
        (Timo: a stopwatch, not a wall-clock timestamp)."""
        if build_start["t"] is not None:
            line = f"{_elapsed_str(build_start['t'])} {line}"
        _log_raw(line)

    def _set_running(running: bool):
        start_btn.configure(state="disabled" if running else "normal")
        # Cancel only makes sense once a subprocess actually exists —
        # _set_subprocess_running() below turns it on once one does
        # (never at the start of _set_running(True), since the copy
        # phase itself has no subprocess to cancel yet).
        cancel_btn.configure(state="disabled")

    def _set_subprocess_running(running: bool):
        cancel_btn.configure(state="normal" if running else "disabled")

    # ── Generic streamed-subprocess runner — used for both the Qt-test
    # gate and build_all.py itself, so the reader-thread/queue-poll
    # machinery exists exactly once. ────────────────────────────────────

    def _reader_thread(proc, q):
        for line in proc.stdout:
            q.put(line.rstrip("\n"))
        returncode = proc.wait()
        q.put(("__DONE__", returncode))

    def _poll_output(q, on_done):
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple) and item[0] == "__DONE__":
                    on_done(item[1])
                    return
                _log(item)
        except queue.Empty:
            pass
        root.after(100, lambda: _poll_output(q, on_done))

    def _run_streamed(cmd: list[str], cwd: Path, on_done):
        env = dict(os.environ)
        # Piping stdout removes the child's real console — without this
        # it can silently fall back to a narrower legacy codepage for
        # its OWN output and crash before anything is even captured,
        # same PYTHONIOENCODING fix compiler/build_all.py's own
        # run_and_tee() already applies for its child processes.
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                # encoding/errors here (not just PYTHONIOENCODING above)
                # — that env var only controls how the CHILD encodes ITS
                # OWN writes; THIS process still decodes whatever bytes
                # come back through the pipe using its own default
                # (locale.getpreferredencoding(), cp1252 on this system)
                # unless told otherwise. Missing this half of the fix
                # crashed _reader_thread below with a real
                # UnicodeDecodeError on a real build run
                # (garmin_collector-3_experiment, Baustein 34) — same
                # two-part fix build_all.py's own run_and_tee() already
                # applies (PYTHONIOENCODING for the child + encoding=
                # "utf-8" for the parent's own Popen() decoding).
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            # `exc` itself is unbound again once this except block ends
            # (Python's own except-variable cleanup) — the lambda below
            # only runs later, via root.after(), so it must close over a
            # plain string instead.
            msg = str(exc)
            root.after(0, lambda: (_log_raw(f"Konnte nicht starten: {msg}"),
                                    on_done(1)))
            return
        proc_state["pid"] = proc.pid
        root.after(0, lambda: _set_subprocess_running(True))
        q: queue.Queue = queue.Queue()
        threading.Thread(target=_reader_thread, args=(proc, q), daemon=True).start()

        def _finish(returncode: int):
            proc_state["pid"] = None
            _set_subprocess_running(False)
            on_done(returncode)

        root.after(0, lambda: _poll_output(q, _finish))

    # ── Copy + Qt-test-gate + build orchestration ───────────────────────
    # Mirrors bat/run_build_all.bat exactly: Qt tests first (aborts the
    # build on failure, same as that .bat's `if errorlevel 1`), then
    # compiler/build_all.py.

    def _finish_all(returncode: int):
        _set_running(False)
        if log_file_handle["fh"] is not None:
            log_file_handle["fh"].close()
            log_file_handle["fh"] = None
        if returncode == 0:
            status_var.set(f"Build fertig — {_elapsed_str(build_start['t'])}")
            _log_raw(f"=== Build erfolgreich beendet ({_elapsed_str(build_start['t'])}) ===")
        else:
            status_var.set(f"Abgebrochen/fehlgeschlagen (Exit {returncode})")
            _log_raw(f"=== Beendet — Exit-Code {returncode} ({_elapsed_str(build_start['t'])}) ===")

    def _start_build_all(src_dir: Path):
        _log_raw("Qt-Tests bestanden — starte build_all.py …")
        status_var.set("Build läuft …")
        _run_streamed([sys.executable, "compiler/build_all.py"], src_dir, _finish_all)

    def _start_qt_test_gate(src_dir: Path):
        status_var.set("Führe Qt-Tests aus …")
        _log_raw("Führe Qt-Tests aus (bat/run_build_all.bat's Gate) …")

        def _on_qt_tests_done(returncode: int):
            if returncode != 0:
                _log_raw("Qt-Tests fehlgeschlagen — Build abgebrochen.")
                _finish_all(returncode)
                return
            _start_build_all(src_dir)

        _run_streamed([sys.executable, "-m", "pytest", "tests/test_qt_app.py", "-v"],
                       src_dir, _on_qt_tests_done)

    def _do_copy_and_build(target: Path):
        def _on_mkdir_retry(attempt: int, total: int):
            root.after(0, lambda: _log_raw(
                f"Zielordner kurzzeitig gesperrt (Windows) — "
                f"erneuter Versuch {attempt}/{total} …"))

        try:
            if target.exists():
                shutil.rmtree(target, onexc=_clear_readonly_and_retry)
            _mkdir_with_retry(target, on_retry=_on_mkdir_retry)
            shutil.copytree(WORK_DIR, target, dirs_exist_ok=True,
                             ignore=_copy_ignore)
        except OSError as exc:
            # Same unbound-except-variable reasoning as _run_streamed()
            # above — capture into a plain string before the lambda.
            msg = str(exc)
            root.after(0, lambda: (_log_raw(f"Kopieren fehlgeschlagen: {msg}"),
                                    _finish_all(1)))
            return

        src_dir = target / "src"
        if not (src_dir / "compiler" / "build_all.py").exists():
            root.after(0, lambda: (
                _log_raw(f"compiler/build_all.py nicht gefunden unter {src_dir} — "
                         "Kopie unvollständig."),
                _finish_all(1),
            ))
            return

        try:
            log_file_handle["fh"] = (target / "build_gui_log.txt").open(
                "w", encoding="utf-8", newline="")
        except OSError:
            log_file_handle["fh"] = None

        root.after(0, lambda: (_log_raw("Kopieren fertig."),
                                _start_qt_test_gate(src_dir)))

    def _on_start():
        target_text = target_var.get().strip()
        if not target_text:
            messagebox.showwarning(
                "🦄 Garmin Local Archiv Builder",
                "Bitte zuerst ein Build-Zielverzeichnis wählen.")
            return
        target = Path(target_text).resolve()
        work = WORK_DIR.resolve()

        # Safety: target must not be (or be inside) the working
        # directory — would copy into itself / delete the source when
        # cleared. And the working directory must not be inside the
        # target — clearing the target would then delete the source.
        target_is_inside_work = False
        try:
            target.relative_to(work)
            target_is_inside_work = True
        except ValueError:
            pass
        work_is_inside_target = False
        try:
            work.relative_to(target)
            work_is_inside_target = True
        except ValueError:
            pass
        if target_is_inside_work or work_is_inside_target:
            messagebox.showerror(
                "🦄 Garmin Local Archiv Builder",
                "Das Build-Zielverzeichnis darf nicht das Arbeitsverzeichnis "
                "sein, nicht darin liegen, und das Arbeitsverzeichnis darf "
                "nicht darin liegen — bitte einen anderen, unabhängigen "
                "Ordner wählen.")
            return

        confirmed = messagebox.askyesno(
            "🦄 Garmin Local Archiv Builder",
            f"Der Inhalt von\n\n{target}\n\nwird vollständig gelöscht und "
            f"durch eine frische Kopie von\n\n{work}\n\nersetzt. Fortfahren?",
        )
        if not confirmed:
            return

        _set_running(True)
        build_start["t"] = time.monotonic()
        _clear_log()
        status_var.set("Kopiere Arbeitsverzeichnis …")
        _log_raw(f"Ziel: {target}")
        _log_raw("Kopiere Arbeitsverzeichnis …")

        threading.Thread(target=_do_copy_and_build, args=(target,), daemon=True).start()

    def _on_cancel():
        pid = proc_state["pid"]
        if pid is None:
            return
        if not messagebox.askyesno(
                "🦄 Garmin Local Archiv Builder",
                "Laufenden Schritt wirklich abbrechen?"):
            return
        _log_raw("Abbruch angefordert …")
        try:
            # /T (Prozessbaum) — sowohl der Qt-Test-Schritt als auch
            # build_all.py starten weitere Kindprozesse (PyInstaller
            # selbst im Fall von build_all.py); ein einfaches
            # Popen.terminate() würde nur den obersten Prozess treffen,
            # dieselbe Lücke, die clients/mcp_process.py::
            # _kill_pid_tree() für den MCP-Server bereits löst.
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True, timeout=20.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log_raw(f"Abbruch fehlgeschlagen: {exc}")

    start_btn.configure(command=_on_start)
    cancel_btn.configure(command=_on_cancel)

    def _on_close():
        if proc_state["pid"] is not None:
            if not messagebox.askyesno(
                    "🦄 Garmin Local Archiv Builder",
                    "Ein Schritt läuft noch — trotzdem schließen? Er läuft "
                    "im Hintergrund weiter, bis er fertig ist oder manuell "
                    "über den Task-Manager beendet wird."):
                return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
