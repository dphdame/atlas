@echo off
REM ==============================================================================
REM From Spoken Words to Countable Data: Meet ATLAS
REM A fast, private way to organize transcripts, count patterns, and trace every quote right on your laptop.
REM 1-Click Desktop Launcher for Windows - 100% Local & Offline
REM ==============================================================================

title From Spoken Words to Countable Data: Meet ATLAS
cd /d "%~dp0"

echo ==================================================================
echo  From Spoken Words to Countable Data: Meet ATLAS
echo  A fast, private way to organize transcripts, count patterns, and trace every quote right on your laptop.
echo  100%% Local Processing - Zero External Network Traffic
echo ==================================================================

REM Check for Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python was not found on your system.
    echo Please install Python 3.10 or higher from: https://www.python.org/downloads/
    echo Be sure to check the box "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM Create local isolated virtual environment if not present
if not exist ".venv" (
    echo --^> Creating local isolated environment (.venv)...
    python -m venv .venv
    echo --^> Installing dependencies into local environment...
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    echo --^> Environment ready.
) else (
    call .venv\Scripts\activate.bat
)

echo --^> Launching ATLAS Desktop Interface in your browser...
echo --^> Close this command prompt window to stop the application.
echo ==================================================================

streamlit run app.py --server.headless=false --browser.serverAddress="localhost"

pause
