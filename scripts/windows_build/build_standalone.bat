@echo off
REM ============================================================================
REM Tiger Motors Digital Twin - Standalone Build Script
REM ============================================================================
REM
REM Builds a portable folder distribution of the GUI application using
REM PyInstaller. The output lives at dist\TigerMotorsDT\ and contains
REM TigerMotorsDT.exe plus every dependency it needs to run on a Windows
REM machine without a Python install.
REM
REM Prerequisites:
REM   - Python 3.10+ on PATH
REM   - .venv at the repo root, with `pip install -e ".[tiger]"` already run
REM   - config.json present (the live config — gitignored; copy and edit
REM     config_template.json if you don't have one yet)
REM
REM Output:
REM   dist\TigerMotorsDT\TigerMotorsDT.exe
REM   dist\TigerMotorsDT\config.json          (user-editable post-install)
REM   dist\TigerMotorsDT\llm_service\         (LLM service config)
REM   dist\TigerMotorsDT\diagrams_and_data\   (Excel log destination)
REM
REM ============================================================================

setlocal enabledelayedexpansion

REM This script lives in <repo_root>\scripts\windows_build\. Move CWD to
REM the repo root so every relative path below resolves the same way
REM whether the .bat was invoked from the repo root, from scripts\windows_build\,
REM or by a double-click.
cd /d "%~dp0..\.."

echo.
echo ============================================================================
echo Tiger Motors Digital Twin - Standalone Build
echo ============================================================================
echo.

REM ----------------------------------------------------------------------------
REM Step 1: Check Python Installation
REM ----------------------------------------------------------------------------

echo [1/8] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    pause
    exit /B 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Found Python %PYTHON_VERSION%
echo.

REM ----------------------------------------------------------------------------
REM Step 2: Check Virtual Environment
REM ----------------------------------------------------------------------------

echo [2/8] Checking virtual environment...

if not exist ".venv" (
    echo ERROR: .venv virtual environment not found
    echo Please create it first with: python -m venv .venv
    echo Then install dependencies: .venv\Scripts\activate ^&^& pip install -e ".[tiger]"
    pause
    exit /B 1
)

echo Virtual environment found
echo.

REM ----------------------------------------------------------------------------
REM Step 3: Activate venv + install PyInstaller if needed
REM ----------------------------------------------------------------------------

echo [3/8] Activating virtual environment and checking PyInstaller...

call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /B 1
)

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /B 1
    )
) else (
    echo PyInstaller already installed
)
echo.

REM ----------------------------------------------------------------------------
REM Step 4: Clean previous build artifacts
REM ----------------------------------------------------------------------------

echo [4/8] Cleaning previous build artifacts...

if exist "build" (
    echo Removing build\ directory...
    rmdir /s /q build
)

if exist "dist\TigerMotorsDT" (
    echo Removing dist\TigerMotorsDT\ directory...
    rmdir /s /q dist\TigerMotorsDT
)

echo Build artifacts cleaned
echo.

REM ----------------------------------------------------------------------------
REM Step 5: Run PyInstaller
REM ----------------------------------------------------------------------------

echo [5/8] Running PyInstaller...
echo This may take several minutes...
echo.

pyinstaller scripts\windows_build\TigerMotorsDT.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed
    echo Check the output above for error details
    pause
    exit /B 1
)

echo PyInstaller build completed successfully
echo.

REM ----------------------------------------------------------------------------
REM Step 6: Copy config + helper files
REM ----------------------------------------------------------------------------
REM
REM PyInstaller's `datas` list in the .spec already copies these into the
REM dist folder, but the explicit copies here are defensive (e.g. if the
REM .spec rule is bypassed for some reason) and they keep the lab's
REM "edit config.json next to the .exe" muscle memory intact.

echo [6/8] Copying configuration files...

if exist "config.json" (
    echo Copying config.json...
    copy /Y config.json dist\TigerMotorsDT\config.json >nul
) else (
    echo WARNING: config.json not found at repo root.
    echo The deployment will use defaults; copy config_template.json next
    echo to TigerMotorsDT.exe and edit the broker IP before running.
)

if exist "config_template.json" (
    echo Copying config_template.json...
    copy /Y config_template.json dist\TigerMotorsDT\config_template.json >nul
)

if not exist "dist\TigerMotorsDT\llm_service" (
    echo Creating llm_service folder...
    mkdir dist\TigerMotorsDT\llm_service
)

if exist "tiger_motors_dt\llm_service\llm_service_config.json" (
    echo Copying llm_service_config.json...
    copy /Y tiger_motors_dt\llm_service\llm_service_config.json dist\TigerMotorsDT\llm_service\llm_service_config.json >nul
)
if exist "tiger_motors_dt\llm_service\llm_service_config_template.json" (
    echo Copying llm_service_config_template.json...
    copy /Y tiger_motors_dt\llm_service\llm_service_config_template.json dist\TigerMotorsDT\llm_service\llm_service_config_template.json >nul
)

if exist "scripts\windows_build\README_STANDALONE.txt" (
    echo Copying README_STANDALONE.txt...
    copy /Y scripts\windows_build\README_STANDALONE.txt dist\TigerMotorsDT\README_STANDALONE.txt >nul
)

if exist "scripts\windows_build\create_shortcut.vbs" (
    echo Copying create_shortcut.vbs...
    copy /Y scripts\windows_build\create_shortcut.vbs dist\TigerMotorsDT\create_shortcut.vbs >nul
)

if not exist "dist\TigerMotorsDT\diagrams_and_data" (
    echo Creating diagrams_and_data folder...
    mkdir dist\TigerMotorsDT\diagrams_and_data
)

echo Configuration files copied
echo.

REM ----------------------------------------------------------------------------
REM Step 7: Write version info
REM ----------------------------------------------------------------------------

echo [7/8] Creating version info...

echo Tiger Motors Digital Twin - Standalone Edition > dist\TigerMotorsDT\version.txt
echo Build Date: %DATE% %TIME% >> dist\TigerMotorsDT\version.txt
echo Python Version: %PYTHON_VERSION% >> dist\TigerMotorsDT\version.txt

git rev-parse --short HEAD >nul 2>&1
if not errorlevel 1 (
    for /f %%i in ('git rev-parse --short HEAD') do set GIT_COMMIT=%%i
    echo Git Commit: !GIT_COMMIT! >> dist\TigerMotorsDT\version.txt
)

echo Version info created
echo.

REM ----------------------------------------------------------------------------
REM Step 8: Remove the intermediate build/ tree
REM ----------------------------------------------------------------------------
REM
REM PyInstaller leaves a TigerMotorsDT.exe in build\TigerMotorsDT\ as a
REM work artifact, but that .exe is NOT runnable (it expects an _internal
REM next to it that only exists in dist\). Deleting build\ after a
REM successful build removes that footgun. The directory will be
REM re-created cleanly on the next build.

echo [8/8] Removing intermediate build\ tree...

if exist "build" (
    rmdir /s /q build
    echo build\ removed
) else (
    echo build\ not present
)
echo.

echo.
echo ============================================================================
echo BUILD COMPLETED SUCCESSFULLY!
echo ============================================================================
echo.
echo Standalone application created at:
echo   %CD%\dist\TigerMotorsDT\
echo.
echo Run with:
echo   %CD%\dist\TigerMotorsDT\TigerMotorsDT.exe
echo.
echo Next Steps:
echo   1. Test the application above (double-click TigerMotorsDT.exe).
echo   2. Create a desktop shortcut: run create_shortcut.vbs in that folder.
echo   3. Edit config.json (next to the .exe) to set your MQTT broker IP.
echo   4. Copy the entire dist\TigerMotorsDT\ folder to deploy on other
echo      Windows machines.
echo.
echo ============================================================================

pause

endlocal
