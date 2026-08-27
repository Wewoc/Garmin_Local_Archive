@echo off
REM support-tools/mcp-call-logger/run_mcp_with_logger.bat
REM
REM Starts mcp_server.py (or mcp_server.exe) on an internal port, plus
REM this proxy on the port Open WebUI is already configured for — see
REM mcp_call_logger.py's own docstring ("Port model") for the full
REM explanation. Open WebUI's tool-server URL never needs to change,
REM whether you use this script or start mcp_server.py the normal way.
REM
REM Two windows open: one for mcp_server.py, one for the proxy. Closing
REM either one stops that half only — close both to fully stop.
REM
REM SETUP: MCP_SERVER_PATH below defaults to ..\..\clients\mcp_server.py
REM (a T1/dev checkout, relative to this script's own folder). Change it
REM if your GLA checkout is laid out differently, or point it at a
REM T3.3 mcp_server.exe instead — both .py and .exe work, this script
REM auto-detects which one you gave it.

setlocal

REM ── Path to your mcp_server.py or mcp_server.exe ─────────────────────
REM Relative paths are resolved against this script's own folder
REM (support-tools\mcp-call-logger\) — ..\..\clients\mcp_server.py points
REM at src\clients\mcp_server.py from here, matching GLA's normal layout.
set MCP_SERVER_PATH=..\..\clients\mcp_server.py

REM ── Internal port — must match INTERNAL_MCP_PORT in logger_config.py ─
set GARMIN_MCP_HTTP_PORT=8758

cd /d "%~dp0"

if not exist "%MCP_SERVER_PATH%" (
    echo.
    echo MCP_SERVER_PATH is not set correctly in this .bat file:
    echo   %MCP_SERVER_PATH%
    echo ^(resolved against %~dp0^)
    echo Edit run_mcp_with_logger.bat and set it to your actual
    echo mcp_server.py or mcp_server.exe location, then run this again.
    echo.
    pause
    exit /b 1
)

REM Auto-detect .py vs .exe — .py needs "python" in front, .exe runs
REM directly. Lets this same script work for both a T1/dev checkout and
REM a T3.3 standalone build without editing the start command below.
set MCP_SERVER_CMD="%MCP_SERVER_PATH%"
if /i "%MCP_SERVER_PATH:~-3%"==".py" set MCP_SERVER_CMD=python "%MCP_SERVER_PATH%"

echo Starting mcp_server.py on internal port %GARMIN_MCP_HTTP_PORT% ...
start "MCP Server (internal, logged)" cmd /k "set GARMIN_MCP_HTTP_PORT=%GARMIN_MCP_HTTP_PORT% && %MCP_SERVER_CMD%"

echo Starting MCP Call Logger ...
start "MCP Call Logger" cmd /k "python mcp_call_logger.py"

echo.
echo Both started in separate windows. Open WebUI's tool-server URL does
echo not need to change.
echo.
echo To go back to normal (no logging): close both windows above, then
echo start mcp_server.py the way you always do.
