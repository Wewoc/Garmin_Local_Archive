@echo off
chcp 65001 > nul
powershell -ExecutionPolicy Bypass -File "%~dp0run_tests.ps1"
pause
