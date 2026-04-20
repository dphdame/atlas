@echo off
REM ATLAS - Setup Script (Windows)
REM Run this once to set up the environment

echo ========================================
echo ATLAS Setup
echo ========================================
echo.

REM Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed.
    echo Please install Python from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version') do echo Found: %%i

REM Check required files exist
if not exist "requirements.txt" (
    echo ERROR: requirements.txt not found. Make sure you are running from the ATLAS folder.
    pause
    exit /b 1
)
if not exist "_pip_helper.py" (
    echo ERROR: _pip_helper.py not found. Make sure you are running from the ATLAS folder.
    pause
    exit /b 1
)

REM Remove broken venv if activate.bat is missing
if exist "venv" (
    if not exist "venv\Scripts\activate.bat" (
        echo Removing broken virtual environment...
        rmdir /s /q venv
    )
)

REM Create virtual environment (without pip to avoid ensurepip crash on restricted machines)
if not exist "venv" (
    echo.
    echo Creating virtual environment...
    python -m venv --without-pip --system-site-packages venv
)

REM Use venv if it was created successfully, otherwise fall back to user install
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
    echo.
    echo Installing packages - this may take a few minutes...
    python _pip_helper.py install -r requirements.txt
) else (
    echo.
    echo Note: Virtual environment unavailable. Using user-level installation.
    echo.
    echo Installing packages - this may take a few minutes...
    python _pip_helper.py install --user -r requirements.txt
)

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Package installation failed. Check the errors above.
    pause
    exit /b 1
)

REM Download NLTK data
echo.
echo Downloading NLTK data...
python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True); nltk.download('stopwords', quiet=True); nltk.download('wordnet', quiet=True); nltk.download('vader_lexicon', quiet=True); print('NLTK data downloaded')"

REM Verify streamlit works
echo.
echo Verifying installation...
python -c "import streamlit; print('Streamlit', streamlit.__version__, '- OK')"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Streamlit did not install correctly.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup complete!
echo ========================================
echo.
echo To run ATLAS, double-click run.bat
echo.
pause
