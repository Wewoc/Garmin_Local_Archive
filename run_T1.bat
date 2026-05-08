@echo off
:: run_T1.bat — Garmin Local Archive · T1 launcher
:: Runs dependency/ecosystem check before starting the app.
:: If check_deps detects relevant changes and user aborts: app does not start.

python tests\check_deps.py
if errorlevel 1 (
    echo.
    echo App start cancelled.
    pause
    exit /b 1
)

python garmin_app.py
