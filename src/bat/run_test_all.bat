@echo off
chcp 65001 > nul
cd /d "%~dp0.."
powershell -ExecutionPolicy Bypass -File "%~dp0..\run_tests.ps1"
pause
