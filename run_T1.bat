@echo off
:: run_T1.bat — Garmin Local Archive · T1 launcher
:: Runs dependency/ecosystem check before starting the app.
:: If check_deps detects relevant changes and user aborts: app does not start.
:: Window stays open after crash or normal exit.

python tests\check_deps.py
if errorlevel 1 (
    echo.
    echo App start cancelled.
    pause
    exit /b 1
)

python garmin_app.py
if errorlevel 1 (
    echo.
    echo === App beendet mit Fehler ^(errorlevel %errorlevel%^) ===
)
pause