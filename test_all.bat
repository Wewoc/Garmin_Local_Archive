@echo off
echo running tests

python tests/test_local.py
python tests/test_local_context.py
python tests/test_dashboard.py
python tests/test_app_logic.py
pytest tests/test_qt_app.py -v
python tests/test_static.py

echo.
pause
