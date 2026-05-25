@echo off
REM ============================================================================
REM OptionsCanvas — Double-click launcher for Windows
REM First run: creates a venv, installs deps, launches the platform
REM Subsequent runs: just launches the platform
REM ============================================================================

setlocal enableextensions

REM Switch to the script's directory so relative paths work regardless of where
REM the user double-clicked from.
cd /d "%~dp0"

title OptionsCanvas
echo ============================================================
echo   OptionsCanvas — starting up
echo ============================================================
echo.

REM ---- 1. Locate Python ------------------------------------------------------
REM NB: inside parenthesized if-blocks, %errorlevel% expands at parse time,
REM not runtime — so we use the `if errorlevel N` keyword form which is
REM always evaluated against the most recent command's exit code.
set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo [ERROR] Python is not installed or not on PATH.
    echo.
    echo Install Python 3.10 or newer from:
    echo     https://www.python.org/downloads/
    echo.
    echo IMPORTANT: tick "Add Python to PATH" in the installer.
    echo.
    pause
    exit /b 1
)

REM ---- 1b. Verify Python is >=3.10 -------------------------------------------
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] OptionsCanvas needs Python 3.10 or newer.
    %PY% --version
    echo.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ---- 2. Create venv on first run ------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [first-run] Creating virtual environment in .venv ...
    %PY% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Failed to create venv. Check the messages above.
    pause
    exit /b 1
)

REM ---- 3. Activate venv -----------------------------------------------------
call ".venv\Scripts\activate.bat"

REM ---- 4. Install / update deps on first run --------------------------------
if not exist ".venv\.deps_installed" (
    echo [first-run] Installing Python dependencies ^(this takes ~2 min^) ...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] pip install failed. Check your internet connection and retry.
        pause
        exit /b 1
    )
    REM Marker file so we don't reinstall on every launch
    echo. > ".venv\.deps_installed"
    echo.
    echo [first-run] Dependencies installed.
    echo.
)

REM ---- 5. Launch the platform -----------------------------------------------
echo Launching OptionsCanvas ... your browser will open at http://localhost:5001
echo ^(Close this window to stop the platform.^)
echo.

python assisted_trading\run_platform.py

REM If the platform exits, pause so the user can see any error message.
echo.
echo OptionsCanvas has stopped.
pause
endlocal
