@echo off
echo Running Qt tests before build...
pytest tests\test_qt_app.py -v
if errorlevel 1 (
    echo.
    echo Qt tests failed — build cancelled.
    pause
    exit /b 1
)

echo.
powershell -NoExit -Command "python .\compiler\build_all.py"