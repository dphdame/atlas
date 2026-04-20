@echo off
REM ATLAS - Run Script (Windows)

REM Activate venv if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Verify streamlit is installed
python -c "import streamlit" >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Streamlit is not installed.
    echo Please run setup.bat first, then try again.
    echo.
    pause
    exit /b 1
)

echo Starting ATLAS Dashboard...
echo Opening in browser at http://localhost:8501
echo.
echo (Press Ctrl+C to stop the dashboard)
echo.
python -m streamlit run app.py

echo.
echo Dashboard stopped.
pause
