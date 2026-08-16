@echo off
REM run_login_probe.bat
REM Starts garmin_login_probe.py from this same folder.
REM Window stays open after the run so LOGIN OK / LOGIN FAILED is
REM readable before closing.

cd /d "%~dp0"
python garmin_login_probe.py

echo.
pause
