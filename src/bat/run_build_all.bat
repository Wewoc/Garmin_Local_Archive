@echo off
cd /d "%~dp0.."

powershell -NoExit -Command "python .\compiler\build_all.py"
