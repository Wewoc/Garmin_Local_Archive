@echo off
chcp 65001 > nul
python "%~dp0tests\check_cve_whitelist.py"
pause