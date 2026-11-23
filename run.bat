@echo off
REM ==============================================================================
REM ATLAS - Automated Text-to-Ledger Actuarial Synthesis
REM Local desktop launcher for Windows
REM
REM Usage:
REM   run.bat               provision .venv if needed, verify, launch ATLAS
REM   run.bat --check-only  provision .venv if needed, verify, exit 0 - no launch, no pause
REM   set ATLAS_NO_LAUNCH=1 same as --check-only
REM
REM Dependencies are reinstalled whenever .venv is missing or the SHA-256 of
REM requirements.txt differs from .venv\.atlas_deps.sha256. The marker is written
REM only after pip succeeds; a failed install removes the incomplete .venv.
REM If the core-import check fails - damaged packages that pip still reports as
REM satisfied - .venv is deleted and rebuilt once; a second failure removes it.
REM Flow uses goto labels instead of parenthesized blocks so echo text with
REM parentheses can never close a block early, and %ERRORLEVEL% is read at run time.
REM Every exit check is an exact comparison with 0: `if errorlevel N` means at least N, so
REM a negative crash status such as -1073741819 would otherwise count as success.
REM ==============================================================================

setlocal EnableExtensions
set "ERRORLEVEL="
title ATLAS Workbench
cd /d "%~dp0"

set "CHECK_ONLY=0"
set "REPAIRED=0"
if "%ATLAS_NO_LAUNCH%"=="1" set "CHECK_ONLY=1"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--check-only" set "CHECK_ONLY=1"
shift
goto parse_args
:args_done

set "VENV_PY=.venv\Scripts\python.exe"
set "MARKER=.venv\.atlas_deps.sha256"
set "HASH_TMP=%TEMP%\atlas_req_hash_%RANDOM%.txt"

echo ==================================================================
echo  ATLAS - Automated Text-to-Ledger Actuarial Synthesis
echo  Local qualitative coding and auditable frequency workbench
echo ==================================================================

REM Check for Python 3.10+
where python >nul 2>nul
if not "%ERRORLEVEL%"=="0" goto no_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if not "%ERRORLEVEL%"=="0" goto old_python

python -c "import hashlib; print(hashlib.sha256(open('requirements.txt', 'rb').read()).hexdigest())" > "%HASH_TMP%"
if not "%ERRORLEVEL%"=="0" goto hash_failed
set /p REQ_HASH=<"%HASH_TMP%"
del "%HASH_TMP%" >nul 2>nul

set "OLD_HASH="
if exist "%MARKER%" set /p OLD_HASH=<"%MARKER%"
if not exist "%VENV_PY%" goto provision
if not "%OLD_HASH%"=="%REQ_HASH%" goto provision
goto verify

:provision
REM An interpreter that exists but cannot run (damaged or not a program) is rebuilt, never handed to pip.
if not exist "%VENV_PY%" goto create_venv
"%VENV_PY%" -c "import sys" >nul 2>nul
if "%ERRORLEVEL%"=="0" goto install_deps
echo --^> Existing .venv interpreter is unusable; rebuilding it...

:create_venv
if exist ".venv" rmdir /s /q ".venv"
echo --^> Creating local isolated environment in .venv ...
python -m venv .venv
if not "%ERRORLEVEL%"=="0" goto venv_failed

:install_deps
echo --^> Installing dependencies into local environment...
"%VENV_PY%" -m pip install --disable-pip-version-check -r requirements.txt --quiet
if "%ERRORLEVEL%"=="0" goto install_ok
echo --^> Standard pip install failed; retrying with the restricted-Windows pip helper...
"%VENV_PY%" _pip_helper.py install --disable-pip-version-check -r requirements.txt --quiet
if not "%ERRORLEVEL%"=="0" goto install_failed

:install_ok
> "%MARKER%" echo %REQ_HASH%
echo --^> Environment ready.

:verify
"%VENV_PY%" -c "import streamlit, pandas, yaml, openpyxl, sklearn, altair, docx, pyarrow"
if not "%ERRORLEVEL%"=="0" goto imports_failed
echo --^> Environment verified: Python, .venv, core imports.
if "%CHECK_ONLY%"=="1" goto check_only_done

echo --^> Launching ATLAS Desktop Interface in your browser...
echo --^> Close this command prompt window to stop the application.
echo ==================================================================
"%VENV_PY%" -m streamlit run app.py --server.headless=false --server.address=localhost --browser.serverAddress=localhost --browser.gatherUsageStats=false
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%

:check_only_done
echo ATLAS check-only: OK - application not launched.
exit /b 0

:no_python
echo ERROR: Python was not found on your system.
echo Please install Python 3.10 or higher from: https://www.python.org/downloads/
echo Be sure to check the box "Add Python to PATH" during installation.
goto fail

:old_python
echo ERROR: ATLAS requires Python 3.10 or higher.
echo Please update Python from: https://www.python.org/downloads/
goto fail

:hash_failed
del "%HASH_TMP%" >nul 2>nul
echo ERROR: Could not read requirements.txt.
goto fail

:venv_failed
if exist ".venv" rmdir /s /q ".venv"
echo ERROR: Could not create the .venv virtual environment.
goto fail

:install_failed
if exist ".venv" rmdir /s /q ".venv"
echo ERROR: Dependency installation failed; the incomplete .venv was removed.
echo Check your connection and run again.
goto fail

:imports_failed
if "%REPAIRED%"=="1" goto imports_failed_again
set "REPAIRED=1"
echo --^> Core imports failed in .venv; rebuilding it from scratch - one attempt...
if exist ".venv" rmdir /s /q ".venv"
goto provision

:imports_failed_again
if exist ".venv" rmdir /s /q ".venv"
echo ERROR: Core imports still fail after rebuilding .venv; it was removed.
echo Check your Python installation and run again.
goto fail

:fail
if not "%CHECK_ONLY%"=="1" pause
exit /b 1
