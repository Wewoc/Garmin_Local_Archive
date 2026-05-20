@echo off
:: run_build_all.bat — Garmin Local Archive · Full Build Launcher (T2 + T3)
:: Runs dependency/ecosystem check before build.
:: If check_deps detects relevant changes and user aborts: build does not start.

echo Running Qt tests before build...
pytest tests\test_qt_app.py -v
if errorlevel 1 (
    echo.
    echo Qt tests failed — build cancelled.
    pause
    exit /b 1
)

echo.
python tests\check_deps.py
if errorlevel 1 (
    echo.
    echo Build cancelled.
    pause
    exit /b 1
)

echo.
set /p CONFIRM="Start full build (T2 + T3)? [j/n]: "
if /i not "%CONFIRM%"=="j" (
    echo.
    echo Build cancelled.
    pause
    exit /b 0
)

echo.
powershell -NoExit -Command "python .\compiler\build_all.py"