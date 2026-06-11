@echo off
REM Tiger Motors Digital Twin - GUI Launcher with Virtual Environment Support
REM Activates the .venv virtual environment and runs the GUI application

echo Starting Tiger Motors Digital Twin GUI...

REM Save current directory
set original_dir=%CD%

REM Set virtual environment path (relative to batch file location)
set venv_root_dir="%~dp0.venv"

REM Check if virtual environment exists
if not exist %venv_root_dir% (
    echo ERROR: Virtual environment not found at %venv_root_dir%
    echo Please create virtual environment first with: python -m venv .venv
    echo Then install requirements with: pip install -r requirements.txt
    pause
    exit /B 1
)

REM Activate virtual environment
echo Activating virtual environment...
call %venv_root_dir%\Scripts\activate.bat

REM Check if activation was successful
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /B 1
)

echo Virtual environment activated successfully
echo.

REM Run the GUI application
echo Launching Tiger Motors Digital Twin GUI...
python gui_main.py

REM Deactivate virtual environment
call %venv_root_dir%\Scripts\deactivate.bat

REM Return to original directory
cd %original_dir%

echo.
echo Tiger Motors Digital Twin GUI has closed.
pause 