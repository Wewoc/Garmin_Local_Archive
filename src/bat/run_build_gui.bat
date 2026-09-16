@echo off
:: run_build_gui.bat — Garmin Local Archive · Build GUI launcher
:: Opens "🦄 Garmin Local Archiv Builder" (compiler/build_gui.py) —
:: pick a build target directory, it copies this working directory
:: there and runs the full build (Qt tests + build_all.py) with a live
:: log. Runs from THIS working directory, never a copy — see
:: compiler/build_gui.py's own module docstring.

cd /d "%~dp0.."

python .\compiler\build_gui.py
