@echo off
REM ============================================================================
REM Tiger Motors Digital Twin - Production Data Generator Launcher
REM ============================================================================
REM This script starts the data generator tool which simulates production
REM line activity by generating MQTT messages for testing purposes.
REM ============================================================================

echo ============================================
echo Tiger Motors Production Data Generator
echo ============================================
echo.

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [WARNING] Virtual environment not found at .venv
    echo Please run: python -m venv .venv
    echo Then install requirements: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Set PYTHONPATH to include the project root
set PYTHONPATH=%~dp0

echo [INFO] Starting data generator...
echo [INFO] Press Ctrl+C to stop the simulation
echo.

REM Run the data generator module
REM You can modify the arguments below or pass them when calling this script
python -m tiger_motors_dt.tools.data_generator %*

REM Deactivate virtual environment
deactivate

echo.
echo [INFO] Data generator finished
pause


