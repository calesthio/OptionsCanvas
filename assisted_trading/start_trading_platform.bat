@echo off
REM OptionsCanvas - Startup Script
REM This script starts the backend server and opens the frontend

echo.
echo ========================================
echo   OptionsCanvas
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

echo [1/3] Checking Python version...
python --version

echo.
echo [2/3] Starting backend server...
echo.
echo Backend will run on http://localhost:5001
echo Keep this window open while using the platform
echo.

REM Start the backend server
cd /d "%~dp0"
python -m backend.chart_api_server

REM If server stops, pause to show error
pause
